"""Device schema declarations never resolve external resources."""

import pytest
from pydantic import ValidationError
from magi.core.device_models import CollectionCapability


@pytest.mark.parametrize("schema", [{"$ref": "https://example.invalid/schema"}, {"$defs": {"x": {"$dynamicRef": "file:///tmp/schema"}}}])
def test_device_schema_rejects_external_resolution(schema):
    with pytest.raises(ValidationError, match="external references"):
        CollectionCapability(capability_id="notes.observe", protocol="source.change.v1", schema_id="notes.item", schema_version=1, payload_schema=schema)
