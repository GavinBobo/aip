# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Entity-relationship canvas API."""

from all_ontology.server.erd.import_export import router as import_export_router
from all_ontology.server.erd.router import router

__all__ = ["import_export_router", "router"]
