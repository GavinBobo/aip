// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// connectionsApi.replaceServerFile — replace a file connection's data from a
// shared-folder file, keeping its catalog name (admin only).
export const PUT = withPermission({ connection: ['manage'] })((req) => proxyToBackend(req));
