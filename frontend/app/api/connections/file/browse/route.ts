// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// connectionsApi.browseServerPaths — list the configured shared folders the
// backend can read (admin only).
export const GET = withPermission({ connection: ['manage'] })((req) => proxyToBackend(req));
