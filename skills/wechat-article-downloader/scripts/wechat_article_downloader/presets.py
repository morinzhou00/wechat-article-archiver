from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccountPreset:
    key: str
    label: str
    sample_url: str
    credential_alias: str


ACCOUNT_PRESETS: tuple[AccountPreset, ...] = (
    AccountPreset(
        key="fupeng-finance",
        label="付鹏的财经世界",
        sample_url=(
            "https://mp.weixin.qq.com/s?"
            "__biz=MzkyNjQzMzY5OQ==&mid=2247491400&idx=1&"
            "sn=9230de0d804cd104431039d7aaaf8fbe"
        ),
        credential_alias="fupeng-finance",
    ),
)

PRESET_BY_KEY = {preset.key: preset for preset in ACCOUNT_PRESETS}
PRESET_BY_LABEL = {preset.label: preset for preset in ACCOUNT_PRESETS}


def preset_for_key(key: str | None) -> AccountPreset | None:
    return PRESET_BY_KEY.get((key or "").strip())


def preset_for_label(label: str | None) -> AccountPreset | None:
    return PRESET_BY_LABEL.get((label or "").strip())

