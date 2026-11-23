// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// erdApi.updateNode — move, resize, collapse or reorder a card (admin only).
export const PATCH = withPermission({ zone: ['manage'] })((req, { user }) =>
	proxyToBackend(req, { userId: user.id }),
);

// erdApi.deleteNode — remove a card and its lines (admin only).
export const DELETE = withPermission({ zone: ['manage'] })((req) => proxyToBackend(req));
