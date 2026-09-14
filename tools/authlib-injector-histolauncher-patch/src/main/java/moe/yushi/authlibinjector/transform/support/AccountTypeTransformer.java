/*
 * Copyright (C) 2023  Haowei Wen <yushijinhun@gmail.com> and contributors
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 * ---------------------------------------------------------------------------
 * Modified by the Histolauncher project on 2026-09-12, based on
 * authlib-injector v1.2.8. Changes in this file:
 *   - Keep --userType mojang on 1.12 and older, where forcing 'msa' breaks
 *     legacy session authentication.
 */

package moe.yushi.authlibinjector.transform.support;

import static moe.yushi.authlibinjector.util.Logging.log;
import static moe.yushi.authlibinjector.util.Logging.Level.INFO;

public class AccountTypeTransformer {

	public String[] transform(String[] args) {
		if (usesLegacySessionUserType(args)) {
			log(INFO, "Keeping accountType as mojang for legacy session auth");
			return args;
		}
		boolean userTypeMatched = false;
		for (int i = 0; i < args.length; i++) {
			String arg = args[i];
			if ("--userType".equals(arg)) {
				userTypeMatched = true;
			} else if (userTypeMatched && "mojang".equals(arg)) {
				args[i] = "msa";
				log(INFO, "Setting accountType to msa");
				break;
			}
		}
		return args;
	}

	private static boolean usesLegacySessionUserType(String[] args) {
		String versionSeries = MainArgumentsTransformer.inferVersionSeries(args).orElse(null);
		if (versionSeries == null || !versionSeries.startsWith("1.")) {
			return false;
		}
		int start = 2;
		int end = start;
		while (end < versionSeries.length() && Character.isDigit(versionSeries.charAt(end))) {
			end++;
		}
		if (end == start) {
			return false;
		}
		try {
			return Integer.parseInt(versionSeries.substring(start, end)) <= 12;
		} catch (NumberFormatException ignored) {
			return false;
		}
	}

}
