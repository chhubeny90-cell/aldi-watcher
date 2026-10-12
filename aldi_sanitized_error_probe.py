"""Run one existing ALDI frontend login probe and retain only sanitized error text.

The underlying frontend probe performs exactly one credential submit and never
activates a refill control. This wrapper adds short TextOutputCallback samples
only after removing configured credentials, phone/email-like identifiers, URLs,
and token-like values. Raw response bodies are never written to disk.
"""

import re

import watcher
import aldi_callback_fidelity_probe as callback_probe
import aldi_frontend_submit_probe as frontend_probe

MAX_SAMPLES = 4
MAX_SAMPLE_LENGTH = 220


def _sanitize_text(value):
    if not isinstance(value, str):
        return None

    text = value
    for secret in (getattr(watcher, "ALDI_USER", ""), getattr(watcher, "ALDI_PASS", "")):
        if isinstance(secret, str) and secret:
            text = text.replace(secret, "[REDACTED]")

    text = re.sub(r"https?://\S+", "[URL]", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "[EMAIL]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?<!\w)(?:\+?\d[\d\s()./-]{5,}\d)(?!\w)", "[PHONE]", text)
    text = re.sub(r"\b[A-Fa-f0-9]{24,}\b", "[TOKEN]", text)
    text = re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "[TOKEN]", text)
    text = " ".join(text.split()).strip()
    if not text:
        return None
    return text[:MAX_SAMPLE_LENGTH]


def _text_output_samples(obj):
    samples = []
    if not isinstance(obj, dict):
        return samples
    for callback in obj.get("callbacks", []):
        if not isinstance(callback, dict) or callback.get("type") != "TextOutputCallback":
            continue
        for item in callback.get("output", []):
            if not isinstance(item, dict):
                continue
            sample = _sanitize_text(item.get("value"))
            if sample and sample not in samples:
                samples.append(sample)
                if len(samples) >= MAX_SAMPLES:
                    return samples
    return samples


_original_shape = callback_probe._shape


def _shape_with_sanitized_text(obj, status=None):
    shape = _original_shape(obj, status)
    shape["sanitized_text_outputs"] = _text_output_samples(obj)
    return shape


def main():
    # aldi_frontend_submit_probe imported _shape by value, so override only its
    # local reference. No production watcher behavior is changed.
    frontend_probe._shape = _shape_with_sanitized_text
    return frontend_probe.main()


if __name__ == "__main__":
    raise SystemExit(main())
