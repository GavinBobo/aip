// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// connectionsApi.updateApi — rewrite a REST connection's settings and fetch it
// again (admin only).
export const PUT = withPermission({ connection: ['manage'] })((req) => proxyToBackend(req));
