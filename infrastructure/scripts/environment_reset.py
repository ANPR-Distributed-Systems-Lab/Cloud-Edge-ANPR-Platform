"""Empty the data of the environment, keeping all its infrastructure: a clean slate for testing.

    python environment_reset.py --prefix anpr-dev                    # only prints what would be deleted
    python environment_reset.py --prefix anpr-dev --confirm anpr-dev # really deletes (--confirm must equal --prefix)

What is emptied (everything is named <prefix>-...):
    database          the schema of the operations database is dropped and recreated (Flyway builds it again
                      when operations-service starts), through the database access host (SSM, see db_tunnel.py)
    DynamoDB tables   every item; the tables stay
    storage bucket    every object; the bucket stays (the models bucket is NOT touched)
    Cognito           EVERY user, devices and people: create your own account again with create_user.py.
                      Access tokens already issued stay valid for up to an hour.
    SQS queues        every message, dead-letter queues included

The ECS services are scaled to 0 while this runs and get their previous task counts back at the end.
The environment must be running (databases available, access host up): start it first.
Safe to run again after a failure: whatever is already empty is left alone.

AWS credentials and region come from the environment (CI: OIDC role; locally: AWS_PROFILE).
"""

import argparse
import os
import re
import shlex
import sys
import time

import boto3
from botocore.exceptions import WaiterError

from environment_power import Environment, batches, fail, log, warn

DYNAMODB_BATCH = 25  # BatchWriteItem accepts at most 25 requests
S3_BATCH = 1000  # DeleteObjects accepts at most 1000 keys
SSM_ONLINE_TIMEOUT_SECONDS = 5 * 60
COMMAND_WAIT = {"Delay": 5, "MaxAttempts": 60}
JDBC_URL = re.compile(r"^jdbc:postgresql://(?P<host>[^:/]+):(?P<port>\d+)/(?P<database>[^?]+)")


def parse_jdbc_url(url):
    match = JDBC_URL.match(url)
    if not match:
        fail(f"cannot read the database address from '{url}'")
    return match["host"], match["port"], match["database"]


def reset_schema_script(host, port, database, user, region, password_parameter):
    """The shell script that runs on the access host. The password is read there and never leaves it."""
    connection = f"host={host} port={port} dbname={database} user={user} sslmode=require"
    return [
        "set -euo pipefail",
        "cloud-init status --wait > /dev/null || true  # a host that has just booted is still installing psql",
        "command -v psql >/dev/null || { echo 'psql is not installed on this host' >&2; exit 1; }",
        f"export PGPASSWORD=\"$(aws ssm get-parameter --region {region} --with-decryption "
        f"--name {shlex.quote(password_parameter)} --query Parameter.Value --output text)\"",
        f"psql {shlex.quote(connection)} -v ON_ERROR_STOP=1 "
        "-c 'DROP SCHEMA public CASCADE' -c 'CREATE SCHEMA public'",
    ]


class Reset:
    def __init__(self, prefix, dry_run):
        self.prefix = prefix
        self.dry_run = dry_run
        self.report = []  # (what, outcome) of every step, for the job summary
        # Services, databases and instances are handled by the same code as in start/stop.
        self.environment = Environment(prefix, prefix, dry_run)
        self.session = boto3.Session()
        self.region = self.session.region_name
        self.sts = boto3.client("sts")
        self.sqs = boto3.client("sqs")
        self.dynamodb = boto3.client("dynamodb")
        self.s3 = boto3.client("s3")
        self.cognito = boto3.client("cognito-idp")
        self.ssm = boto3.client("ssm")

        # Names of the operations database and its credentials, as Terraform creates them for <prefix>.
        self.database_id = f"{prefix}-operations"
        self.ssm_prefix = f"/anpr/{prefix.split('-', 1)[1]}/operations-service"

    # ------------------------------------------------------------ the whole reset

    def run(self):
        host = self.require_running_environment()

        described = self.environment.describe_services(self.environment.service_names())
        services = {s["serviceName"]: s["desiredCount"] for s in described}
        for name in services:
            self.environment.set_desired_count(name, 0)
        self.environment.wait_for_services(list(services))

        try:
            self.reset_database(host)
            self.clear_tables()
            self.empty_bucket()
            self.delete_users()
            self.purge_queues()  # last: events that arrived while the rest was being emptied go as well
        finally:
            for name, count in services.items():  # back to what it was, also after a failure
                self.environment.set_desired_count(name, count)
            self.environment.wait_for_services(list(services))

        log("Done." if not self.dry_run else "Dry run finished, nothing was changed.")
        self.write_summary()
        if not self.dry_run:
            warn("All Cognito users were deleted: create your account again with create_user.py.")

    def record(self, what, outcome):
        """Logs one step and keeps it for the summary. `outcome` is what was (or would be) done."""
        log(f"{what}: {outcome}")
        self.report.append((what, outcome))

    def write_summary(self):
        """The result as a table on the workflow run page (GitHub job summary)."""
        title = "Dry run: NOTHING was changed" if self.dry_run else "Reset done"
        lines = [f"### {title}", "", "| What | Result |", "|---|---|"]
        lines += [f"| {what} | {outcome} |" for what, outcome in self.report]
        if self.dry_run:
            lines += ["", f"Run the workflow again with `{self.prefix}` typed in the field to delete this."]
        else:
            lines += ["", "All Cognito users are gone: create your account again with create_user.py."]

        text = "\n".join(lines)
        print(text, flush=True)
        summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_file:
            with open(summary_file, "a", encoding="utf-8") as f:
                f.write(text + "\n")

    def require_running_environment(self):
        status = self.environment.database_status(self.database_id)
        if status != "available":
            fail(f"{self.database_id} is '{status}'. Start the environment first (workflow 'Start environment').")
        running = [i for i in self.environment.instances() if i["state"] == "running"]
        if not running:
            fail("The database access host is not running. Start the environment first.")
        return running[0]["id"]

    # ------------------------------------------------------------ database

    def reset_database(self, host):
        url = self.parameter("datasource-url")
        user = self.parameter("datasource-username")
        db_host, port, database = parse_jdbc_url(url)
        password_parameter = f"{self.ssm_prefix}/datasource-password"
        script = reset_schema_script(db_host, port, database, user, self.region, password_parameter)

        done = "would be dropped and recreated" if self.dry_run else "dropped and recreated"
        outcome = f"schema 'public' of database '{database}' {done}"
        if self.dry_run:
            self.record(self.database_id, outcome)
            return
        self.wait_until_online(host)
        command_id = self.ssm.send_command(
            InstanceIds=[host], DocumentName="AWS-RunShellScript", Parameters={"commands": script}
        )["Command"]["CommandId"]
        try:
            waiter = self.ssm.get_waiter("command_executed")
            waiter.wait(CommandId=command_id, InstanceId=host, WaiterConfig=COMMAND_WAIT)
        except WaiterError:
            result = self.ssm.get_command_invocation(CommandId=command_id, InstanceId=host)
            fail(f"database reset failed ({result['Status']}): {result['StandardErrorContent'].strip()}")

    def parameter(self, name):
        return self.ssm.get_parameter(Name=f"{self.ssm_prefix}/{name}")["Parameter"]["Value"]

    def wait_until_online(self, instance_id):
        """A freshly started instance needs a minute before its SSM agent accepts commands."""
        deadline = time.time() + SSM_ONLINE_TIMEOUT_SECONDS
        while True:
            info = self.ssm.describe_instance_information(Filters=[{"Key": "InstanceIds", "Values": [instance_id]}])
            if any(i["PingStatus"] == "Online" for i in info["InstanceInformationList"]):
                return
            if time.time() > deadline:
                minutes = SSM_ONLINE_TIMEOUT_SECONDS // 60
                fail(f"{instance_id} did not register with Systems Manager within {minutes} minutes")
            time.sleep(10)

    # ------------------------------------------------------------ DynamoDB

    def table_names(self):
        names = []
        for page in self.dynamodb.get_paginator("list_tables").paginate():
            names += page["TableNames"]
        return sorted(n for n in names if n.startswith(f"{self.prefix}-"))

    def item_keys(self, table):
        """The primary keys of every item, page by page (only the key attributes are read)."""
        schema = self.dynamodb.describe_table(TableName=table)["Table"]["KeySchema"]
        names = {f"#k{i}": element["AttributeName"] for i, element in enumerate(schema)}
        for page in self.dynamodb.get_paginator("scan").paginate(
            TableName=table, ProjectionExpression=", ".join(names), ExpressionAttributeNames=names
        ):
            yield page["Items"]

    def clear_tables(self):
        for table in self.table_names():
            deleted = 0
            for items in self.item_keys(table):
                deleted += len(items)
                if self.dry_run:
                    continue
                for group in batches(items, DYNAMODB_BATCH):
                    self.delete_items(table, group)
            self.record(table, f"{deleted} item(s) {'would be deleted' if self.dry_run else 'deleted'}")

    def delete_items(self, table, keys):
        requests = [{"DeleteRequest": {"Key": key}} for key in keys]
        while requests:  # DynamoDB may return part of the batch unprocessed
            response = self.dynamodb.batch_write_item(RequestItems={table: requests})
            requests = response.get("UnprocessedItems", {}).get(table, [])

    # ------------------------------------------------------------ S3

    def empty_bucket(self):
        account = self.sts.get_caller_identity()["Account"]
        bucket = f"{self.prefix}-storage-{account}"
        deleted = 0
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            deleted += len(keys)
            if keys and not self.dry_run:
                for group in batches(keys, S3_BATCH):
                    self.s3.delete_objects(Bucket=bucket, Delete={"Objects": group, "Quiet": True})
        self.record(bucket, f"{deleted} object(s) {'would be deleted' if self.dry_run else 'deleted'}")

    # ------------------------------------------------------------ Cognito

    def user_pool_id(self):
        pools = []
        for page in self.cognito.get_paginator("list_user_pools").paginate(MaxResults=60):
            pools += [p["Id"] for p in page["UserPools"] if p["Name"] == self.prefix]
        if len(pools) != 1:
            fail(f"expected exactly one Cognito user pool named '{self.prefix}', found {len(pools)}")
        return pools[0]

    def delete_users(self):
        pool = self.user_pool_id()
        deleted = 0
        # Collected first: deleting while paging through the list could skip users.
        pages = self.cognito.get_paginator("list_users").paginate(UserPoolId=pool)
        usernames = [user["Username"] for page in pages for user in page["Users"]]
        for username in usernames:
            deleted += 1
            if not self.dry_run:
                self.cognito.admin_delete_user(UserPoolId=pool, Username=username)
        self.record(f"Cognito pool {pool}", f"{deleted} user(s) {'would be deleted' if self.dry_run else 'deleted'}")

    # ------------------------------------------------------------ SQS

    def queue_urls(self):
        urls = []
        for page in self.sqs.get_paginator("list_queues").paginate(QueueNamePrefix=f"{self.prefix}-"):
            urls += page.get("QueueUrls", [])
        return sorted(urls)

    def purge_queues(self):
        for url in self.queue_urls():
            waiting = self.sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])
            count = waiting["Attributes"]["ApproximateNumberOfMessages"]
            done = "would be purged" if self.dry_run else "purged"
            self.record(url.rsplit("/", 1)[-1], f"about {count} message(s) {done}")
            if self.dry_run:
                continue
            try:
                self.sqs.purge_queue(QueueUrl=url)
            except self.sqs.exceptions.PurgeQueueInProgress:  # SQS allows one purge per queue and minute
                warn(f"{url}: a purge is already running")


def main():
    parser = argparse.ArgumentParser(description="Empty the data of the environment, keeping its infrastructure.")
    parser.add_argument("--prefix", required=True, help="name prefix of the environment, e.g. anpr-dev")
    parser.add_argument("--confirm", help="repeat the prefix to really delete; without it nothing is changed")
    args = parser.parse_args()

    if args.confirm is not None and args.confirm != args.prefix:
        parser.error(f"--confirm must be '{args.prefix}'")

    dry_run = args.confirm is None
    if dry_run:
        log("No --confirm: only printing what would be deleted.")
    Reset(args.prefix, dry_run).run()


if __name__ == "__main__":
    sys.exit(main())
