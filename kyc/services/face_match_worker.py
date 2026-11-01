"""Isolated biometric inference; inputs stay in pipes, never temporary files."""

import base64
import io
import json
import sys
from contextlib import redirect_stdout


def main():
    payload = json.load(sys.stdin)
    # Keep library startup/progress output out of the JSON result stream.
    with redirect_stdout(sys.stderr):
        import numpy as np
        from deepface import DeepFace
        from PIL import Image

        document = Image.open(io.BytesIO(base64.b64decode(payload["document"]))).convert("RGB")
        selfie = Image.open(io.BytesIO(base64.b64decode(payload["selfie"]))).convert("RGB")
        result = DeepFace.verify(
            img1_path=np.array(document),
            img2_path=np.array(selfie),
            model_name="VGG-Face",
            enforce_detection=True,
        )
    print(json.dumps({"distance": float(result["distance"]), "verified": bool(result["verified"])}))


if __name__ == "__main__":
    main()
