// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// parsingApi.testLayout — probe the D-FINE layout service.
export const POST = withPermission({ catalog: ['edit'] })((req) => proxyToBackend(req));
