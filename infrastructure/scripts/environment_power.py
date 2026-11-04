"""Switch the environment on or off: its ECS services and its RDS databases.

    python environment_power.py start   [--dry-run]
    python environment_power.py stop    [--dry-run]
    python environment_power.py status

start   databases first (services need them), then every service with the number of
        tasks from its "finops:start-count" tag (set by Terraform as start_count)
stop    every service to 0 tasks first, then the databases
status  prints the current state as tables (also written to the GitHub job summary)

Safe to run repeatedly: anything already in the wanted state is left alone.
--dry-run only prints what would change.

Configuration (command-line option or environment variable):
    --cluster    / ECS_CLUSTER       ECS cluster whose services are switched, e.g. anpr-dev
    --db-prefix  / RDS_NAME_PREFIX   RDS instances named "<prefix>-*" are switched, e.g. anpr-dev
AWS credentials and region come from the environment (CI: OIDC role; locally: AWS_PROFILE).
"""

import argparse
import os
import sys
import time

import boto3

START_COUNT_TAG = "finops:start-count"

# DescribeServices and the services_stable waiter accept at most 10 services per call.
SERVICES_PER_CALL = 10

DB_POLL_SECONDS = 20
DB_TIMEOUT_SECONDS = 25 * 60

# RDS states nobody can fix from here; a human has to look at the instance.
BROKEN_DB_STATES = ("failed", "incompatible-", "inaccessible-encryption-credentials", "storage-full")


def log(message):
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


def warn(message):
    # In GitHub Actions this becomes a yellow annotation on the run page.
    print(f"::warning::{message}" if os.environ.get("GITHUB_ACTIONS") else f"WARNING: {message}", flush=True)


def fail(message):
    print(f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"ERROR: {message}", flush=True)
    sys.exit(1)


def name_of(arn):
    """arn:aws:ecs:<region>:<account>:service/<cluster>/<name> -> <name>"""
    return arn.split("/")[-1]


def batches(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


class Environment:
    def __init__(self, cluster, db_prefix, dry_run):
        self.cluster = cluster
        self.db_prefix = db_prefix
        self.dry_run = dry_run
        self.ecs = boto3.client("ecs")
        self.rds = boto3.client("rds")

    # ------------------------------------------------------------ the three commands

    def start(self):
        databases = self.database_ids()
        log(f"Databases with prefix '{self.db_prefix}-': {len(databases)}")
        for db in databases:
            self.start_database(db)
        for db in databases:  # services must not start before the databases accept connections
            log(f"{db}: waiting until available")
            self.wait_for_database(db, "available")

        arns = self.service_arns()
        log(f"Services in cluster '{self.cluster}': {len(arns)}")
        changed = [name_of(arn) for arn in arns if self.start_service(arn)]
        self.wait_for_services(changed)

    def stop(self):
        services = self.service_names()
        log(f"Services in cluster '{self.cluster}': {len(services)}")
        changed = [name for name in services if self.stop_service(name)]
        self.wait_for_services(changed)  # tasks are gone before the databases go down

        databases = self.database_ids()
        log(f"Databases with prefix '{self.db_prefix}-': {len(databases)}")
        for db in databases:
            self.stop_database(db)
        # Stopping an RDS instance finishes a few minutes later on the AWS side. We do not
        # wait for that: instance hours stop being billed once it reaches "stopped".

    def status(self):
        lines = ["### Databases", "| Database | Status |", "|---|---|"]
        for db in self.database_ids():
            lines.append(f"| {db} | {self.database_status(db)} |")

        lines += ["", "### Services", "| Service | Desired | Running |", "|---|---|---|"]
        for service in self.describe_services(self.service_names()):
            lines.append(f"| {service['serviceName']} | {service['desiredCount']} | {service['runningCount']} |")

        text = "\n".join(lines)
        print(text, flush=True)
        summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_file:  # the job summary shown on the workflow run page
            with open(summary_file, "a", encoding="utf-8") as f:
                f.write(text + "\n")

    # ------------------------------------------------------------ the only place that changes anything

    def apply(self, description, api_call, **parameters):
        """Every change goes through here, so --dry-run is guaranteed to change nothing."""
        if self.dry_run:
            log(f"DRY-RUN: {description}")
        else:
            api_call(**parameters)

    # ------------------------------------------------------------ databases

    def database_ids(self):
        ids = []
        for page in self.rds.get_paginator("describe_db_instances").paginate():
            ids += [db["DBInstanceIdentifier"] for db in page["DBInstances"]]
        return sorted(i for i in ids if i.startswith(f"{self.db_prefix}-"))

    def database_status(self, db):
        return self.rds.describe_db_instances(DBInstanceIdentifier=db)["DBInstances"][0]["DBInstanceStatus"]

    def wait_for_database(self, db, wanted):
        if self.dry_run:
            return
        deadline = time.time() + DB_TIMEOUT_SECONDS
        while self.database_status(db) != wanted:
            if time.time() > deadline:
                fail(f"{db} did not reach status '{wanted}' within {DB_TIMEOUT_SECONDS // 60} minutes")
            time.sleep(DB_POLL_SECONDS)

    def fail_if_broken(self, db, status):
        if status.startswith(BROKEN_DB_STATES):
            fail(f"{db} is in state '{status}'; fix it in the AWS console first")

    def start_database(self, db):
        status = self.database_status(db)
        self.fail_if_broken(db, status)

        if status == "stopping":  # an instance cannot be started while it is still stopping
            log(f"{db}: stopping, waiting for it to stop first")
            self.wait_for_database(db, "stopped")
            status = "stopped"

        if status == "stopped":
            log(f"{db}: starting")
            self.apply(f"start database {db}", self.rds.start_db_instance, DBInstanceIdentifier=db)
        else:
            log(f"{db}: {status}, nothing to start")

    def stop_database(self, db):
        status = self.database_status(db)
        self.fail_if_broken(db, status)

        if status in ("stopped", "stopping"):
            log(f"{db}: already {status}")
            return

        if status == "starting":  # an instance cannot be stopped while it is still starting
            log(f"{db}: starting, waiting until available first")
            self.wait_for_database(db, "available")

        log(f"{db}: stopping")
        self.apply(f"stop database {db}", self.rds.stop_db_instance, DBInstanceIdentifier=db)

    # ------------------------------------------------------------ services

    def service_arns(self):
        arns = []
        for page in self.ecs.get_paginator("list_services").paginate(cluster=self.cluster):
            arns += page["serviceArns"]
        return sorted(arns)

    def service_names(self):
        return [name_of(arn) for arn in self.service_arns()]

    def describe_services(self, names):
        services = []
        for group in batches(names, SERVICES_PER_CALL):
            services += self.ecs.describe_services(cluster=self.cluster, services=group)["services"]
        return services

    def wait_for_services(self, names):
        if self.dry_run or not names:
            return
        log(f"Waiting for {len(names)} service(s) to become stable")
        waiter = self.ecs.get_waiter("services_stable")
        for group in batches(names, SERVICES_PER_CALL):
            waiter.wait(cluster=self.cluster, services=group, WaiterConfig={"Delay": 15, "MaxAttempts": 60})

    def start_count(self, arn):
        """The tag set by Terraform: how many tasks this service runs when the environment is on."""
        name = name_of(arn)
        tags = {t["key"]: t["value"] for t in self.ecs.list_tags_for_resource(resourceArn=arn)["tags"]}
        value = tags.get(START_COUNT_TAG)

        if value is None:
            warn(f"{name} has no '{START_COUNT_TAG}' tag; using 1. Set start_count in Terraform.")
            return 1
        if not value.isdigit():
            fail(f"{name} has an invalid '{START_COUNT_TAG}' tag: '{value}' (expected a whole number)")
        return int(value)

    def set_desired_count(self, name, wanted):
        """Returns True when something was changed."""
        current = self.describe_services([name])[0]["desiredCount"]
        if current == wanted:
            log(f"{name}: already {current} task(s)")
            return False

        log(f"{name}: {current} -> {wanted} task(s)")
        self.apply(
            f"set {name} to {wanted} task(s)",
            self.ecs.update_service,
            cluster=self.cluster,
            service=name,
            desiredCount=wanted,
        )
        return True

    def start_service(self, arn):
        name = name_of(arn)
        wanted = self.start_count(arn)
        if wanted == 0:
            log(f"{name}: start-count is 0, left as it is")
            return False
        return self.set_desired_count(name, wanted)

    def stop_service(self, name):
        return self.set_desired_count(name, 0)


def main():
    parser = argparse.ArgumentParser(description="Switch the environment on or off.")
    parser.add_argument("command", choices=["start", "stop", "status"])
    parser.add_argument("--cluster", default=os.environ.get("ECS_CLUSTER"))
    parser.add_argument("--db-prefix", default=os.environ.get("RDS_NAME_PREFIX"))
    parser.add_argument("--dry-run", action="store_true", help="print the changes instead of making them")
    args = parser.parse_args()

    if not args.cluster or not args.db_prefix:
        parser.error("set --cluster and --db-prefix (or ECS_CLUSTER and RDS_NAME_PREFIX)")

    environment = Environment(args.cluster, args.db_prefix, args.dry_run)
    getattr(environment, args.command)()


if __name__ == "__main__":
    main()
