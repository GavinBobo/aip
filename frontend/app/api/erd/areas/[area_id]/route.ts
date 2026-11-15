// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// erdApi.updateArea — move, resize or rename a grouping rectangle (admin only).
export const PATCH = withPermission({ zone: ['manage'] })((req, { user }) =>
	proxyToBackend(req, { userId: user.id }),
);

// erdApi.deleteArea — remove a grouping rectangle (admin only).
export const DELETE = withPermission({ zone: ['manage'] })((req) => proxyToBackend(req));
