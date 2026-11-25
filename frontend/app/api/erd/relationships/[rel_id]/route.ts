// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// erdApi.updateRelationship — change cardinality, label or columns (admin only).
export const PATCH = withPermission({ zone: ['contribute'] })((req, { user }) =>
	proxyToBackend(req, { userId: user.id }),
);

// erdApi.deleteRelationship — remove one line (admin only).
export const DELETE = withPermission({ zone: ['contribute'] })((req) => proxyToBackend(req));
