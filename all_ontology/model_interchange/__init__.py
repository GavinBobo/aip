# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Neutral model-interchange document types and embedding helpers.

This package belongs to neither the HTTP layer nor the data-access layer: the
DAL reads and writes the document, the server transports it, and both need the
same schema and embed-row builders.
"""
