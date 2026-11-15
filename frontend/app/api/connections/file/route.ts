// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// connectionsApi.createFile — register an uploaded file as a connection
// (admin only; carries the file and its chosen shape).
export const POST = withPermission({ connection: ['manage'] })((req) => proxyToBackend(req));
