# Scripts

Python tools for working with the deployed `dev` environment. Every example below is run from the repository root
in PowerShell. Each script also explains itself: `python <script> --help`, and its docstring.

## Before the first run

```powershell
pip install -r infrastructure/scripts/requirements.txt   # boto3
aws sso login --profile dev                               # the AWS session, repeat when it expires
```

- Scripts in `identity/` read the ids and URLs from the Terraform outputs, so `terraform` must be on the PATH.
- `environment/db_tunnel.py` also needs the Session Manager plugin: `winget install Amazon.SessionManagerPlugin`.
- `--profile dev` can be left out when `$env:AWS_PROFILE = "dev"` is set.

## Layout

| Folder | What it is for |
|---|---|
| `environment/` | Switching the environment on and off, emptying its data, reaching its database |
| `identity/` | Accounts of people and devices, and checks that use them (`api_client.py` is their shared helper) |
| `tests/` | pytest tests of all of the above, with AWS and the API replaced by stubs |

## environment/

The three workflows run these scripts in CI (`Start environment`, `Stop environment`, `Reset environment`);
locally the same code runs against whatever the AWS session points at.

### environment_power.py: start, stop and look at the environment

Switches the RDS databases, the database access host (EC2) and the ECS services. Safe to run again: whatever is
already in the wanted state is left alone. `--dry-run` only prints what would change.

```powershell
$env:ECS_CLUSTER = "anpr-dev"; $env:RDS_NAME_PREFIX = "anpr-dev"   # or --cluster / --db-prefix

python infrastructure/scripts/environment/environment_power.py status
python infrastructure/scripts/environment/environment_power.py start --dry-run
python infrastructure/scripts/environment/environment_power.py stop
```

### environment_reset.py: empty the data, keep the infrastructure

Empties the operations database, the DynamoDB tables, the storage bucket, **every Cognito user** and the SQS
queues; the models bucket is not touched. Without `--confirm` it only prints what would be deleted. The environment
must be running.

```powershell
python infrastructure/scripts/environment/environment_reset.py --prefix anpr-dev                      # dry run
python infrastructure/scripts/environment/environment_reset.py --prefix anpr-dev --confirm anpr-dev   # deletes
```

Afterwards create your account again with `identity/create_user.py`.

### db_tunnel.py: reach the private database from this computer

Opens a port-forwarding session through the database access host (SSM, no SSH) and prints the connection details.
Keep the window open, Ctrl+C closes the tunnel. In pgAdmin or psql use the host `127.0.0.1` (not `localhost`),
port `5433`, database `operations`.

```powershell
python infrastructure/scripts/environment/db_tunnel.py --profile dev
```

The password is read with the command the script prints (`aws ssm get-parameter --with-decryption ...`).

## identity/

People and devices live in the Cognito user pool of the environment (`docs/identity-and-access.md`).

### create_user.py: create the account of a person

Asks for the password twice (it has to meet the policy of the pool).

```powershell
python infrastructure/scripts/identity/create_user.py kamil --profile dev
```

It prints the account id (Cognito `sub`).

### create_device.py: pair an edge device with a person, or delete it

Writes the generated credentials to `--out`, which must be **outside** the repository.

```powershell
python infrastructure/scripts/identity/create_device.py --person-username kamil --out C:\secrets\rpi-01.json --profile dev
python infrastructure/scripts/identity/create_device.py --delete <deviceId> --profile dev
```

#### Putting the credentials on the Pi

The device reads its login from `/config/device-credentials.json` in the Docker volume `rpi-edge_rpi-edge-config`
on the Pi. The Docker context `rpi` (SSH to the Pi, see `rpi-edge/RASPBERRY_PI_SETUP.md`, step 6) lets you do it from
this computer. Run the commands from the `rpi-edge/` folder.

**After a reset of the environment** (the old device no longer exists):

1. Stop the container and remove its volumes. `rpi-edge_rpi-edge-config` holds the old credentials and the cached
   configuration, `rpi-edge_rpi-edge-state` the unsent events, photos and the model cache. None of it fits a new
   `deviceId`. To keep the model cache, remove only the `config` volume.

   ```powershell
   cd G:\repos\Cloud-Edge-ANPR-Platform\rpi-edge
   docker --context rpi compose down
   docker --context rpi volume rm rpi-edge_rpi-edge-config rpi-edge_rpi-edge-state
   ```

2. Create the new device (above). Build the image, create the container without starting it and copy the file in,
   so detection cannot start before the credentials are there.

   ```powershell
   docker --context rpi compose create --build
   docker --context rpi compose cp C:\secrets\rpi-01.json rpi-edge:/config/device-credentials.json
   ```

3. Start it and follow the log.

   ```powershell
   docker --context rpi compose up -d
   docker --context rpi compose logs -f
   ```

**Replacing only the credentials** needs no restart, because the app reads the file at every sign-in. Use the `cp`
command of step 2; if the container does not exist yet, go through a throw-away one:

```powershell
docker --context rpi create --name credentials-copy -v rpi-edge_rpi-edge-config:/config alpine
docker --context rpi cp C:\secrets\rpi-01.json credentials-copy:/config/device-credentials.json
docker --context rpi rm credentials-copy
```

Check the file without printing it (it holds the password), then delete the local copy:

```powershell
docker --context rpi run --rm -v rpi-edge_rpi-edge-config:/config alpine ls -l /config/device-credentials.json
Remove-Item C:\secrets\rpi-01.json
```

### check_platform.py: see what the platform shows the owner of a device

Signs in as the person (password from `$env:CHECK_PLATFORM_PASSWORD` or asked for) and reads the device, the latest
detections or the alerts. Plate numbers are masked unless `--show-plates` is given. The `dev` web client does not
allow password sign-in, so add `--admin-auth` there.

```powershell
python infrastructure/scripts/identity/check_platform.py --username kamil --admin-auth --profile dev device
python infrastructure/scripts/identity/check_platform.py --username kamil --admin-auth --profile dev detections --limit 10
python infrastructure/scripts/identity/check_platform.py --username kamil --admin-auth --profile dev alert --list
```

## Tests

```powershell
pip install pytest boto3
python -m pytest infrastructure/scripts
```

No AWS access is needed. `pytest.ini` puts `environment/` and `identity/` on the import path.
