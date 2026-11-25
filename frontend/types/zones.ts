// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export type Zone = {
	id: string;
	name: string;
	label: string;
	description: string | null;
	color: string | null;
	enabled: boolean;
	access?: ZoneAccess;
};

export type ZoneAccessUser = {
	id: string;
	name: string;
	email: string;
	role: string | null;
};

export type ZoneAccessDepartment = {
	id: string;
	name: string;
};

export type ZoneAccess = {
	user_ids: string[];
	dept_ids: string[];
	users: ZoneAccessUser[];
	departments: ZoneAccessDepartment[];
	grants?: ZoneGrant[];
	user_permissions?: Record<string, ZonePermission>;
	dept_permissions?: Record<string, ZonePermission>;
};

export type ZonePermission = 'read' | 'edit' | 'manage';

export type ZoneGrant = {
	subject_type: 'user' | 'department';
	subject_id: string;
	permission: ZonePermission;
	expires_at?: string | null;
};

export type ZoneItem = {
	id: string;
	name: string;
	label: string;
};

export type ZoneDetail = Zone & {
	items: ZoneItem[];
};

/** Returned by POST /zones — items is a list of linked IDs, not full objects. */
export type ZoneCreated = Zone & {
	items: string[];
};

export type ZoneCreateInput = {
	name: string;
	description?: string;
	color: string;
	items: string[];
};

export type ZoneUpdateInput = {
	name?: string;
	description?: string | null;
	color?: string | null;
	items?: string[];
};

export type ZoneAccessInput = {
	grants: ZoneGrant[];
	user_ids?: string[];
	dept_ids?: string[];
};
