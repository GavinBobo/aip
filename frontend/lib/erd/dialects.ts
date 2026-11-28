// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { SqlDialect } from '@/types/erd';

/** Export/parse dialects, in the order the picker shows them. */
export const SQL_DIALECTS: { value: SqlDialect; label: string }[] = [
	{ value: 'sqlserver', label: 'SQL Server' },
	{ value: 'postgres', label: 'PostgreSQL' },
	{ value: 'mysql', label: 'MySQL' },
	{ value: 'mariadb', label: 'MariaDB' },
	{ value: 'oracle', label: 'Oracle' },
	{ value: 'sqlite', label: 'SQLite' },
];
