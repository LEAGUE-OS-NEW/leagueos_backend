"""Isolated biometric inference; inputs stay in pipes, never temporary files."""

import base64
import io
import json
import sys
from contextlib import redirect_stdout


def decode_bgr(encoded):
    """Normalize phone orientation and return pixels in DeepFace's BGR order."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(base64.b64decode(encoded))) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
        red, green, blue = image.split()
        return Image.merge("RGB", (blue, green, red))


def main():
    payload = json.load(sys.stdin)
    # Keep library startup/progress output out of the JSON result stream.
    with redirect_stdout(sys.stderr):
        import numpy as np
        from deepface import DeepFace

        document = decode_bgr(payload["document"])
        selfie = decode_bgr(payload["selfie"])
        result = DeepFace.verify(
            img1_path=np.array(document),
            img2_path=np.array(selfie),
            model_name="VGG-Face",
            enforce_detection=True,
        )
    print(json.dumps({"distance": float(result["distance"]), "verified": bool(result["verified"])}))


if __name__ == "__main__":
    main()
