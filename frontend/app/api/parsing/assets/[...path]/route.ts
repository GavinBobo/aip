// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// Extracted pictures referenced by the parsed Markdown. Same gate as the rest of
// the parsing surface, and the bytes are relayed untouched — decoding an image
// as text is how uploads get corrupted.
export const GET = withPermission({ catalog: ['edit'] })((req) => proxyToBackend(req));
