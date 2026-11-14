"""Open a tunnel from this computer to a private database, through the database access host (SSM, no SSH).

    python db_tunnel.py [--profile dev] [--port 5433] [--database anpr-dev-operations]

While it runs, connect pgAdmin (or psql) to 127.0.0.1:<port>. Ctrl+C closes the tunnel.
Use the address 127.0.0.1, not the name localhost: the tunnel listens on IPv4 only, and clients try the IPv6
address of localhost first, which times out.
The database and the access host must be running (the "Start environment" workflow switches both on).

The script prints the user name and the command that reads the password; it never prints the password.
Local port 5433 by default, so it does not clash with a local PostgreSQL on 5432.

Needs the AWS CLI and its Session Manager plugin (winget install Amazon.SessionManagerPlugin), and AWS
credentials (locally: aws sso login --profile dev).
"""

import argparse
import shutil
import subprocess
import sys

import boto3

SWITCH_TAG = "finops:switch"  # set on the access host by Terraform (infrastructure/modules/db-access-host)
SSM_DOCUMENT = "AWS-StartPortForwardingSessionToRemoteHost"
DEFAULT_DATABASE = "anpr-dev-operations"
DEFAULT_SSM_PREFIX = "/anpr/dev/operations-service"


def running_access_host(ec2):
    """The id of the running instance that carries the switch tag."""
    response = ec2.describe_instances(
        Filters=[
            {"Name": f"tag:{SWITCH_TAG}", "Values": ["true"]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )
    ids = [i["InstanceId"] for r in response["Reservations"] for i in r["Instances"]]
    if not ids:
        sys.exit("No running access host. Start the environment first (workflow 'Start environment').")
    return ids[0]


def available_database(rds, database_id):
    """(address, port) of the database, if it is running."""
    instance = rds.describe_db_instances(DBInstanceIdentifier=database_id)["DBInstances"][0]
    if instance["DBInstanceStatus"] != "available":
        sys.exit(f"{database_id} is {instance['DBInstanceStatus']}, not available. Start the environment first.")
    return instance["Endpoint"]["Address"], instance["Endpoint"]["Port"]


def main():
    parser = argparse.ArgumentParser(description="Tunnel to a private database through the access host.")
    parser.add_argument("--profile", help="AWS profile (default: the environment's)")
    parser.add_argument("--port", type=int, default=5433, help="local port to listen on")
    parser.add_argument("--database", default=DEFAULT_DATABASE, help="RDS instance identifier")
    parser.add_argument("--ssm-prefix", default=DEFAULT_SSM_PREFIX, help="SSM path of the database's credentials")
    args = parser.parse_args()

    if not shutil.which("session-manager-plugin"):
        sys.exit("The Session Manager plugin is missing: winget install Amazon.SessionManagerPlugin")

    session = boto3.Session(profile_name=args.profile)
    host = running_access_host(session.client("ec2"))
    address, remote_port = available_database(session.client("rds"), args.database)
    user = session.client("ssm").get_parameter(Name=f"{args.ssm_prefix}/datasource-username")["Parameter"]["Value"]

    profile_option = f" --profile {args.profile}" if args.profile else ""
    print(f"Tunnel to {args.database} through {host}.")
    print(f"  pgAdmin / psql: host 127.0.0.1 (not localhost), port {args.port}, database operations, user {user}")
    print("  password: aws ssm get-parameter --with-decryption --query Parameter.Value --output text "
          f"--name {args.ssm_prefix}/datasource-password{profile_option}")
    print("Ctrl+C closes the tunnel.", flush=True)

    command = ["aws", "ssm", "start-session", "--target", host, "--document-name", SSM_DOCUMENT,
               "--parameters", f"host={address},portNumber={remote_port},localPortNumber={args.port}"]
    if args.profile:
        command += ["--profile", args.profile]
    try:
        subprocess.run(command, check=False)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
