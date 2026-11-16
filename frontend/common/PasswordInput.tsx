// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState, type InputHTMLAttributes } from 'react';
import { Icon, IconName } from '@/common/icons';
import { t } from '@/i18n';

type PasswordInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & {
	/** The form's own input classes; the reveal button's inset is added here. */
	inputClassName: string;
};

/**
 * Password field with a reveal toggle. The text stays in the DOM and only the
 * input's `type` changes, so form state, autofill and validation all behave
 * exactly as they do for a plain password input.
 */
export const PasswordInput = ({ inputClassName, disabled, ...props }: PasswordInputProps) => {
	const [revealed, setRevealed] = useState(false);
	const label = revealed ? t('Hide password') : t('Show password');

	return (
		<div className="relative">
			<input
				{...props}
				disabled={disabled}
				type={revealed ? 'text' : 'password'}
				className={`${inputClassName} pr-10`}
			/>
			<button
				type="button"
				onClick={() => setRevealed((current) => !current)}
				aria-label={label}
				aria-pressed={revealed}
				title={label}
				disabled={disabled}
				className="absolute inset-y-0 right-0 flex w-10 cursor-pointer items-center justify-center rounded-r-md text-secondary transition-colors hover:text-heading focus-visible:ring-2 focus-visible:ring-[#76b900]/40 focus-visible:outline-none focus-visible:ring-inset disabled:cursor-not-allowed disabled:opacity-50 dark:text-zinc-400 dark:hover:text-zinc-200"
			>
				<Icon
					name={revealed ? IconName.EyeOff : IconName.Eye}
					aria-hidden
					className="h-4 w-4"
				/>
			</button>
		</div>
	);
};
