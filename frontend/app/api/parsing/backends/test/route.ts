// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// parsingApi.testBackend — probe the recognition endpoint from the server, so
// the browser never needs to reach it (and never sees its credential).
export const POST = withPermission({ catalog: ['edit'] })((req) => proxyToBackend(req));
