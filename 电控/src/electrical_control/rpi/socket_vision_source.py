"""Live vision source bridging MaixCAM BATCH_TARGETS into the Scheduler.

A listener thread (:func:`vision_listener`) receives the frozen BATCH_TARGETS
data region over TCP and calls :meth:`SocketVisionSource.ingest`. The scheduler
then pulls :class:`ItemTaskContext` one item at a time through the same
``set_permitted()/next_if_permitted()`` protocol as ``FakeTaskSource``.

Design points (2026-09-05 bridge review, 4-role council):
  * Single-slot "latest batch": BATCH_TARGETS is a full-scene snapshot, so a
    new batch replaces any un-consumed one (no stale FIFO, no cross-batch
    target_seq collision).
  * ``box_id = class_id`` placeholder: class_id already encodes colour x shape
    (frozen), so the only thing left for calibration is the real
    ``(colour, shape) -> box_id -> drop point`` map.
  * batch ``task_id`` is validated against the verified round; a mismatch
    (including the unconfigured 0) is dropped fail-closed so a stale/foreign
    round can never leak items into the active round.
"""

from __future__ import annotations

import socket
import threading
from dataclasses import replace
from typing import Callable

from electrical_control.rpi import ItemTaskContext
from electrical_control.rpi.vision_ingest import (
    BatchTargets,
    build_item_task_queue,
    parse_batch_targets,
)

# BATCH_TARGETS wire layout (interface-contract sec. 5.1):
#   target_count(1) + task_id(2, BE) + target[N]
# where each target is 7 bytes. The header encodes the total length, so the
# receiver self-delimits on the count byte (TCP is a byte stream, not messages).
_BATCH_HEADER_BYTES = 3
_BATCH_TARGET_BYTES = 7


def _recv_exact(conn: socket.socket, nbytes: int) -> bytes | None:
    """Receive exactly ``nbytes`` bytes, or None on EOF (peer closed)."""
    buf = bytearray()
    while len(buf) < nbytes:
        chunk = conn.recv(nbytes - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def recv_batch(conn: socket.socket) -> bytes | None:
    """Read one self-delimiting BATCH_TARGETS region from a stream socket.

    Reads 1 count byte, then the ``2 + 7*count`` remaining bytes. Works for
    both the current per-frame short connection and a long-lived connection.
    """
    count_byte = _recv_exact(conn, 1)
    if count_byte is None:
        return None
    count = count_byte[0]
    rest = _recv_exact(conn, (_BATCH_HEADER_BYTES - 1) + count * _BATCH_TARGET_BYTES)
    if rest is None:
        return None
    return count_byte + rest


class SocketVisionSource:
    """Live, thread-safe vision source conforming to the FakeTaskSource seam."""

    def __init__(
        self,
        *,
        round_id: str,
        task_id: int,
        image_id_for_class: Callable[[int], int],
        drop_point_for_box: Callable[[int], tuple[int, int]],
    ) -> None:
        self._round_id = round_id
        self._task_id = task_id
        self._image_id_for_class = image_id_for_class
        self._drop_point_for_box = drop_point_for_box
        self._permitted = False
        self._lock = threading.Lock()
        self._latest: BatchTargets | None = None
        self._pending: list[ItemTaskContext] = []
        self._frame_seq = 0

    def set_permitted(self, permitted: bool) -> None:
        self._permitted = permitted

    def next_if_permitted(self) -> ItemTaskContext | None:
        if not self._permitted:
            return None
        with self._lock:
            if not self._pending:
                batch = self._latest
                self._latest = None
                if batch is None:
                    return None
                self._pending = self._expand(batch)
            return self._pending.pop(0)

    def _expand(self, batch: BatchTargets) -> list[ItemTaskContext]:
        # box_id placeholder: class_id already encodes colour x shape, so
        # box_id = class_id until the real (colour, shape) -> box_id map lands.
        filled = BatchTargets(
            task_id=batch.task_id,
            targets=tuple(replace(t, box_id=t.class_id) for t in batch.targets),
        )
        payloads = build_item_task_queue(
            filled,
            image_id_for_class=self._image_id_for_class,
            drop_point_for_box=self._drop_point_for_box,
        )
        contexts: list[ItemTaskContext] = []
        for payload in payloads:
            self._frame_seq += 1
            contexts.append(
                ItemTaskContext(
                    round_id=self._round_id,
                    task_id=self._task_id,
                    frame_seq=self._frame_seq,
                    payload=payload,
                )
            )
        return contexts

    def ingest(self, data: bytes) -> None:
        """Parse and stage one BATCH_TARGETS region (thread-safe, fail-closed).

        Malformed / out-of-contract batches are dropped whole; a batch whose
        ``task_id`` does not match the verified round is dropped as well, so a
        stale round never leaks items into the active one.
        """
        try:
            batch = parse_batch_targets(data)
        except Exception:
            # fail-closed: malformed region is dropped, never half-consumed.
            return
        if batch.task_id != self._task_id:
            # fail-closed: stale/foreign round (including unconfigured task_id 0).
            return
        with self._lock:
            self._latest = batch


def vision_listener(
    source: SocketVisionSource,
    *,
    host: str = "0.0.0.0",
    port: int = 8765,
    stop_event: threading.Event | None = None,
) -> None:
    """Blocking TCP listener: accept MaixCAM, stream BATCH_TARGETS into source.

    Run as a daemon thread. Accepts one peer at a time and reads self-delimited
    batches until the peer closes (works for both the current per-frame short
    connection and the long-lived connection).
    """
    stop = stop_event or threading.Event()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)
    server.settimeout(1.0)
    try:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(1.0)
                while not stop.is_set():
                    data = recv_batch(conn)
                    if data is None:
                        break
                    source.ingest(data)
    finally:
        server.close()


__all__ = [
    "SocketVisionSource",
    "recv_batch",
    "vision_listener",
]
