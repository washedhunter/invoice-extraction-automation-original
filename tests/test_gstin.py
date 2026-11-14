import pytest

from invoice_tool import gstin

# GSTINs published as examples in public GST documentation and tutorials.
KNOWN_VALID = ["27AAPFU0939F1ZV", "29AAGCB7383J1Z4"]


@pytest.mark.parametrize("value", KNOWN_VALID)
def test_known_valid(value):
    assert gstin.validate(value) is None


def test_checksum_mismatch_detected():
    assert "checksum" in gstin.validate("27AAPFU0939F1ZX")


@pytest.mark.parametrize(
    "value, reason",
    [
        ("27AAPFU0939F1Z", "length"),
        ("27AAPF10939F1ZV", "bad format"),
        ("27AAPFU0939F1AV", "bad format"),  # 14th character must be Z
        ("45AAPFU0939F1ZV", "state code"),
        ("", "missing"),
        (None, "missing"),
    ],
)
def test_invalid_reasons(value, reason):
    assert reason in gstin.validate(value)


def test_normalise_strips_spaces_and_case():
    assert gstin.validate(" 27aapfu0939f1zv ") is None
    assert gstin.normalise("27 AAPFU-0939F1ZV") == "27AAPFU0939F1ZV"


def test_state_code():
    assert gstin.state_code("27AAPFU0939F1ZV") == "27"
    assert gstin.state_code("27AAPFU0939F1ZX") == "27"  # still usable when checksum fails
    assert gstin.state_code("ZZ") is None
    assert gstin.state_code(None) is None
