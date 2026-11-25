// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// erdApi.importCanvas — replace or merge a diagram from JSON/DBML (admin only).
export const POST = withPermission({ zone: ['contribute'] })((req, { user }) =>
	proxyToBackend(req, { userId: user.id }),
);
