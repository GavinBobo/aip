// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

type EditableTargetLike = {
	tagName?: string;
	isContentEditable?: boolean;
};

/** Whether a keyboard event target should keep the browser's native editing keys. */
export const isEditableTarget = (target: EditableTargetLike | null | undefined): boolean => {
	if (!target) return false;
	const tag = target.tagName;
	return (
		tag === 'INPUT' ||
		tag === 'TEXTAREA' ||
		tag === 'SELECT' ||
		target.isContentEditable === true
	);
};
