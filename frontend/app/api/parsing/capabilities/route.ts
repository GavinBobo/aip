// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// parsingApi.capabilities — backend state and accepted option values.
export const GET = withPermission({ catalog: ['edit'] })((req) => proxyToBackend(req));
