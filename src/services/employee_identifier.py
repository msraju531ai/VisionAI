from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass
class FaceEmbeddingResult:
    embedding: list[float]
    bbox_xywh: tuple[int, int, int, int]


class EmployeeIdentifier:
    """Face detection + deep-learning embedding + cosine similarity matcher.

    Uses DeepFace (Facenet model) for reliable face recognition across
    varying lighting, angles, and video quality.
    """

    # Lazy-load DeepFace to avoid slow import at startup
    _deepface = None

    def __init__(self, model_name: str = "Facenet"):
        self._model_name = model_name

    @classmethod
    def _get_deepface(cls):
        if cls._deepface is None:
            from deepface import DeepFace  # noqa: PLC0415
            cls._deepface = DeepFace
        return cls._deepface

    def detect_and_embed(self, bgr_image: np.ndarray) -> Optional[FaceEmbeddingResult]:
        if bgr_image is None or bgr_image.size == 0:
            return None

        try:
            DeepFace = self._get_deepface()
            # DeepFace expects BGR or RGB; pass enforce_detection=False so it
            # doesn't raise when no face is found.
            results = DeepFace.represent(
                img_path=bgr_image,
                model_name=self._model_name,
                enforce_detection=False,
                detector_backend="opencv",
            )
            if not results:
                return None

            # Pick the highest-confidence (or largest) face
            best = max(results, key=lambda r: r.get("face_confidence", 0.0))

            if best.get("face_confidence", 1.0) == 0.0 and len(results) == 1:
                # enforce_detection=False can return a zero-confidence result
                # when no face was actually detected — skip it
                fa = best.get("facial_area", {})
                # If the facial area covers the entire image it's a fallback; accept it
                # only if the image itself looks like a face (small crop passed in)
                ih, iw = bgr_image.shape[:2]
                fa_w = fa.get("w", 0)
                fa_h = fa.get("h", 0)
                if fa_w >= iw * 0.95 and fa_h >= ih * 0.95:
                    # whole-image fallback on a face crop — accept
                    pass
                else:
                    return None

            emb = best["embedding"]
            fa = best.get("facial_area", {})
            x = int(fa.get("x", 0))
            y = int(fa.get("y", 0))
            w = int(fa.get("w", bgr_image.shape[1]))
            h = int(fa.get("h", bgr_image.shape[0]))
            return FaceEmbeddingResult(embedding=emb, bbox_xywh=(x, y, w, h))

        except Exception:
            return None

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        va = np.asarray(a, dtype=np.float32)
        vb = np.asarray(b, dtype=np.float32)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        if denom <= 1e-9:
            return 0.0
        return float(np.dot(va, vb) / denom)

    def match_employee(
        self,
        embedding: list[float],
        employees: list[tuple[int, str, list[float]]],
        threshold: float,
    ) -> Optional[tuple[int, str, float]]:
        best: Optional[tuple[int, str, float]] = None
        for emp_id, emp_name, emp_emb in employees:
            score = self.cosine_similarity(embedding, emp_emb)
            if best is None or score > best[2]:
                best = (emp_id, emp_name, score)

        if best is None:
            return None
        if best[2] < threshold:
            return None
        return best