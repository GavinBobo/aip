// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// explorationApi.getPairModeAnalysis — Zone-scoped relationship graph for the
// human/agent relationship workspace.
export const GET = withPermission({ catalog: ['read'] })((req) => proxyToBackend(req));
