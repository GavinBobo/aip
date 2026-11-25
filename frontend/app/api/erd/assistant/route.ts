// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// erdApi.askAssistant — the canvas chat bubble. An LLM call, but no writes:
// the answer is a list of edits the browser applies through the normal routes,
// so the permission that matters is the same one those routes need.
export const POST = withPermission({ zone: ['contribute'] })((req, { user }) =>
	proxyToBackend(req, { userId: user.id }),
);
