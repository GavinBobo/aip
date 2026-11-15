// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// connectionsApi.previewApi — call a REST endpoint once so the wizard can show
// its rows and offer the rename step (admin only).
export const POST = withPermission({ connection: ['manage'] })((req) => proxyToBackend(req));
