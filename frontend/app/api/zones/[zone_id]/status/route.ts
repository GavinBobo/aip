// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// zonesApi.setEnabled — enable/disable a zone; the backend checks manage.
export const PATCH = withPermission({ zone: ['contribute'] })((req) => proxyToBackend(req));
