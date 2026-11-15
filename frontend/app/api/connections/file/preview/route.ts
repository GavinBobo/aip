// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// connectionsApi.previewFile — read the first rows of an upload so the wizard
// can offer the header row and column renames (admin only).
export const POST = withPermission({ connection: ['manage'] })((req) => proxyToBackend(req));
