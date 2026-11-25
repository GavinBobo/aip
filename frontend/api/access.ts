// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { requests } from './requests';
import type { ApiResponse, ResponseWithError } from './types';
import type { AccessUser, Department, DepartmentWriteInput, MyAccess } from '@/types/access';

export const accessApi = {
	me: (): Promise<ResponseWithError<{ data: MyAccess }>> => requests.get('access/me'),

	departments: (): Promise<ApiResponse<Department[]>> => requests.get('access/departments'),

	createDepartment: (
		input: DepartmentWriteInput,
	): Promise<ResponseWithError<{ data: Department }>> =>
		requests.post('access/departments', input),

	updateDepartment: (
		deptId: string,
		input: DepartmentWriteInput,
	): Promise<ResponseWithError<{ data: Department }>> =>
		requests.patch(`access/departments/${deptId}`, input),

	deleteDepartment: (deptId: string): Promise<ResponseWithError<{ data: { id: string } }>> =>
		requests.delete(`access/departments/${deptId}`),

	users: (): Promise<ApiResponse<AccessUser[]>> => requests.get('access/users'),

	setUserDepartments: (
		userId: string,
		deptIds: string[],
	): Promise<ResponseWithError<{ data: { user_id: string; departments: Department[] } }>> =>
		requests.put(`access/users/${userId}/departments`, { dept_ids: deptIds }),
};
