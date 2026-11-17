"""Every message the detection mode exchanges with the platform, as typed, immutable dataclasses.

  direction  module            type                 endpoint                                counterpart
  in         configuration.py  DeviceConfiguration  GET /api/v1/device/config               device-management
  in         models.py         DeviceModels         GET /api/v1/device/models               device-management
  in         alerts.py         AlertList            GET /api/v1/alerts                      operations-service
  out        ingest.py         DetectionBatch       POST /api/v1/ingest/detections          ingest Lambda
  out        locations.py      LocationBatch        POST /api/v1/ingest/device-locations    ingest Lambda
  out        metrics.py        MetricsBatch         POST /api/v1/device/metrics             device-management
  out / in   images.py         ImageUploadRequest   POST /api/v1/images/presigned-urls      device-management
                               / ImageUploadUrls
  in         problem.py        Problem              any error answer (RFC 9457)             all of them

wire.py holds what they share (ids, timestamps). The field names on the wire are those of the contracts
(device-management-service/device-management-api.yaml, docs/api/): camelCase. Incoming documents become
dataclasses through from_document(), which checks every field (parsing.py) and raises ContractError naming each
problem; outgoing ones become JSON through to_document(). No other module reads or builds a raw document.
"""
