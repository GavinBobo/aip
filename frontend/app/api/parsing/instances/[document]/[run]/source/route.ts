// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// The file a run parsed, for the detail view's 原始文件 tab. Relayed as bytes.
export const GET = withPermission({ catalog: ['edit'] })((req) => proxyToBackend(req));
