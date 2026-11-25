// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// erdApi.getCanvas — read one zone's diagram (any viewer may look).
export const GET = withPermission({ zone: ['read'] })((req) => proxyToBackend(req));

// erdApi.updateViewport — remember where the canvas was scrolled (admin only).
export const PATCH = withPermission({ zone: ['contribute'] })((req, { user }) =>
	proxyToBackend(req, { userId: user.id }),
);
