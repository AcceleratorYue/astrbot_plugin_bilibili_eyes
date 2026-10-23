"""音频转录接口桩。

当前版本不做 ASR；保留统一接口，后续接入 Whisper/其它 provider 时替换实现即可。
"""

from __future__ import annotations

from pathlib import Path


class AudioTranscriber:
    async def transcribe(self, audio_path: Path) -> list[tuple[float, str]]:
        """返回 [(开始秒数, 文本)]；当前版本故意抛 NotImplementedError。"""

        raise NotImplementedError("音频转录暂未实现，只保留接口桩")
