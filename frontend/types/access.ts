// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export type AccessMember = {
	id: string;
	name: string;
	email: string;
	role: string | null;
};

export type Department = {
	id: string;
	name: string;
	description: string;
	created: string;
	users: AccessMember[];
	user_ids: string[];
};

export type DepartmentWriteInput = {
	name: string;
	description: string | null;
	user_ids: string[];
};

export type AccessUser = AccessMember & {
	banned: boolean;
	dept_ids: string[];
};

export type MyAccess = {
	user_id: string;
	role: string | null;
	is_admin: boolean;
	dept_ids: string[];
	/** `null` for an admin, who is deliberately unscoped. */
	zone_ids: string[] | null;
	zone_permissions: Record<string, 'read' | 'edit' | 'manage'> | null;
};
