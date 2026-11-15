// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// erdApi.restoreVersion — put a saved version back (admin only).
export const POST = withPermission({ zone: ['manage'] })((req, { user }) =>
	proxyToBackend(req, { userId: user.id }),
);
