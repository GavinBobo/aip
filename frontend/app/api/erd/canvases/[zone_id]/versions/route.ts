// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// erdApi.listVersions — saved snapshots of a canvas (any viewer may look).
export const GET = withPermission({ zone: ['read'] })((req) => proxyToBackend(req));

// erdApi.createVersion — snapshot the canvas (admin only).
export const POST = withPermission({ zone: ['contribute'] })((req, { user }) =>
	proxyToBackend(req, { userId: user.id }),
);
