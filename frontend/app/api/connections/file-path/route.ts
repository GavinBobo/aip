// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// connectionsApi.createServerFile — catalogue a file from a shared folder
// without uploading it through the browser (admin only).
export const POST = withPermission({ connection: ['manage'] })((req) => proxyToBackend(req));
