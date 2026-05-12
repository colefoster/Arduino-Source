"""Vocabulary maps for embedding indices."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class Vocabulary:
    """Maps string tokens to integer indices for embedding layers."""

    PAD = "<PAD>"
    UNK = "<UNK>"

    def __init__(self):
        self.token_to_idx: dict[str, int] = {self.PAD: 0, self.UNK: 1}
        self.idx_to_token: dict[int, str] = {0: self.PAD, 1: self.UNK}
        self.frozen: bool = False

    def add(self, token: str) -> int:
        if token in self.token_to_idx:
            return self.token_to_idx[token]
        if self.frozen:
            return self.token_to_idx[self.UNK]
        idx = len(self.token_to_idx)
        self.token_to_idx[token] = idx
        self.idx_to_token[idx] = token
        return idx

    def __getitem__(self, token: str) -> int:
        if token in self.token_to_idx:
            return self.token_to_idx[token]
        return self.token_to_idx[self.UNK]

    def __len__(self) -> int:
        return len(self.token_to_idx)

    def __contains__(self, token: str) -> bool:
        return token in self.token_to_idx

    def freeze(self):
        self.frozen = True

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.token_to_idx, f)

    @classmethod
    def load(cls, path: Path) -> Vocabulary:
        v = cls()
        with open(path) as f:
            v.token_to_idx = json.load(f)
        v.idx_to_token = {i: t for t, i in v.token_to_idx.items()}
        v.frozen = True
        return v


@dataclass
class Vocabs:
    species: Vocabulary = field(default_factory=Vocabulary)
    moves: Vocabulary = field(default_factory=Vocabulary)
    abilities: Vocabulary = field(default_factory=Vocabulary)
    items: Vocabulary = field(default_factory=Vocabulary)
    weather: Vocabulary = field(default_factory=Vocabulary)
    terrain: Vocabulary = field(default_factory=Vocabulary)
    status: Vocabulary = field(default_factory=Vocabulary)

    def freeze_all(self):
        for v in self._all():
            v.freeze()

    def save(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        for name, vocab in self._named():
            vocab.save(directory / f"{name}.json")

    @classmethod
    def load(cls, directory: Path) -> Vocabs:
        vocabs = cls()
        for name, _ in vocabs._named():
            path = directory / f"{name}.json"
            if path.exists():
                setattr(vocabs, name, Vocabulary.load(path))
        return vocabs

    def _all(self) -> list[Vocabulary]:
        return [v for _, v in self._named()]

    def _named(self) -> list[tuple[str, Vocabulary]]:
        return [
            ("species", self.species),
            ("moves", self.moves),
            ("abilities", self.abilities),
            ("items", self.items),
            ("weather", self.weather),
            ("terrain", self.terrain),
            ("status", self.status),
        ]
