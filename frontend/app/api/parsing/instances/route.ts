// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// parsingApi.instances — the stored parse runs, newest first.
export const GET = withPermission({ catalog: ['edit'] })((req) => proxyToBackend(req));
