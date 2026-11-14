"""Every message the detection mode exchanges with the platform, as typed, immutable dataclasses.

  direction  module            type                 endpoint                               counterpart
  in         configuration.py  DeviceConfiguration  GET /api/v1/device/config              device-management
  in         models.py         DeviceModels         GET /api/v1/device/models              device-management
  in         alerts.py         AlertList            GET /api/v1/alerts                     operations-service
  out        ingest.py         DetectionBatch       POST /api/v1/ingest/detections         ingest Lambda
  in         problem.py        Problem              any error answer (RFC 9457)            all of them

The field names on the wire are those of the contracts (device-management-service/device-management-api.yaml,
docs/api/ingest-detections.md): camelCase. Incoming documents become dataclasses through from_document(), which
checks every field (parsing.py) and raises ContractError naming each problem; outgoing ones become JSON through
to_document(). No other module reads or builds a raw document.
"""
