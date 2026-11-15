// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { proxyToBackend } from '@/auth/proxy-backend';
import { withPermission } from '@/auth/with-auth';

// explorationApi.getTablePreview — a bounded sample of a table's rows, read
// from its live source.
export const GET = withPermission({ catalog: ['read'] })((req) => proxyToBackend(req));
