# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from all_ontology.knowledge.context import _MAX_TOKENS, _tokens


def test_chinese_tokens_are_the_2_3_4_grams_in_order() -> None:
    # 采购订单金额
    tokens = _tokens("\u91c7\u8d2d\u8ba2\u5355\u91d1\u989d")

    assert tokens[:5] == ["\u91c7\u8d2d", "\u8d2d\u8ba2", "\u8ba2\u5355", "\u5355\u91d1", "\u91d1\u989d"]
    assert tokens[5:9] == [
        "\u91c7\u8d2d\u8ba2",
        "\u8d2d\u8ba2\u5355",
        "\u8ba2\u5355\u91d1",
        "\u5355\u91d1\u989d",
    ]
    assert tokens[9:] == [
        "\u91c7\u8d2d\u8ba2\u5355",
        "\u8d2d\u8ba2\u5355\u91d1",
        "\u8ba2\u5355\u91d1\u989d",
    ]


def test_token_budget_stops_at_the_limit() -> None:
    question = "\u91c7\u8d2d\u8ba2\u5355\u91d1\u989d\u5206\u5e03" * 5

    tokens = _tokens(question)

    assert len(tokens) == _MAX_TOKENS
    assert len({token.casefold() for token in tokens}) == len(tokens)
