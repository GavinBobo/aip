// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Button } from '@/common/Button';
import { Modal } from '@/common/modal/Modal';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';

export type ConfirmRequest = {
	title: string;
	message: string;
	confirmLabel: string;
	onConfirm: () => void;
};

type ConfirmDialogProps = {
	request: ConfirmRequest | null;
	onClose: () => void;
};

/**
 * An in-app confirmation. The native `confirm()` blocks the renderer — a stuck
 * dialog there freezes the whole canvas, which is a poor trade for a delete.
 */
export const ConfirmDialog = ({ request, onClose }: ConfirmDialogProps) => (
	<Modal open={request != null} onClose={onClose} className="w-full max-w-md">
		{request && (
			<div className="p-5">
				<h2 className="text-base font-semibold text-heading dark:text-zinc-100">
					{request.title}
				</h2>
				<p className="mt-2 text-sm text-body dark:text-zinc-300">{request.message}</p>
				<div className="mt-4 flex justify-end gap-2">
					<Button theme={ButtonTheme.Secondary} size={Size.REGULAR} onClick={onClose}>
						{t('Cancel')}
					</Button>
					<Button
						theme={ButtonTheme.Danger}
						size={Size.REGULAR}
						onClick={() => {
							request.onConfirm();
							onClose();
						}}
					>
						{request.confirmLabel}
					</Button>
				</div>
			</div>
		)}
	</Modal>
);
