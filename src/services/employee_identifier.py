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
    """Lightweight face detection + embedding + cosine similarity matcher.

    This is intentionally self-contained for demo usage and does not affect the RTSP pipeline.
    """

    def __init__(self, face_size: int = 64):
        self._face_size = face_size
        self._cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

    def _largest_face(self, faces: np.ndarray) -> Optional[tuple[int, int, int, int]]:
        if faces is None or len(faces) == 0:
            return None
        faces_sorted = sorted(faces, key=lambda f: int(f[2]) * int(f[3]), reverse=True)
        x, y, w, h = faces_sorted[0]
        return int(x), int(y), int(w), int(h)

    def detect_and_embed(self, bgr_image: np.ndarray) -> Optional[FaceEmbeddingResult]:
        if bgr_image is None or bgr_image.size == 0:
            return None

        gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
        bbox = self._largest_face(faces)
        if bbox is None:
            return None

        x, y, w, h = bbox
        face = bgr_image[y : y + h, x : x + w]
        emb = self._embed_face(face)
        if emb is None:
            return None

        return FaceEmbeddingResult(embedding=emb, bbox_xywh=bbox)

    def _embed_face(self, face_bgr: np.ndarray) -> Optional[list[float]]:
        if face_bgr is None or face_bgr.size == 0:
            return None

        face_gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
        face_resized = cv2.resize(face_gray, (self._face_size, self._face_size), interpolation=cv2.INTER_AREA)
        vec = face_resized.astype(np.float32).reshape(-1)

        norm = float(np.linalg.norm(vec))
        if norm <= 1e-9:
            return None
        vec = vec / norm
        return vec.tolist()

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
