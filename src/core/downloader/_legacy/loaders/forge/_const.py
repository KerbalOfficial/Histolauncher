from __future__ import annotations

from typing import Tuple


NETWORK_FAILURE_MARKERS: Tuple[str, ...] = (
    "failed to validate certificates",
    "unsupported or unrecognized ssl message",
    "error checking https://",
    "sslhandshakeexception",
    "unable to tunnel through proxy",
)


LOG4J_INCOMPATIBLE_MARKERS: Tuple[str, ...] = (
    "TerminalConsole",
    "LoggerNamePatternSelector",
    "%highlightForge",
    "%minecraftFormatting",
    "net.minecrell.terminalconsole",
)


MAVEN_REPOS: Tuple[str, ...] = (
    "https://maven.minecraftforge.net/",
    "https://libraries.minecraft.net/",
    "https://repo1.maven.org/maven2/",
)


MODLAUNCHER_FALLBACK_VERSIONS: Tuple[str, ...] = (
    "9.1.3", "9.1.2", "9.1.1", "9.1.0", "9.0.17", "9.0.16", "8.1.26",
)


FALLBACK_LOG4J_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Configuration status="warn" packages="net.minecraftforge.fml.loading.moddiscovery" shutdownHook="disable">
    <Appenders>
        <Console name="Console" target="SYSTEM_OUT" follow="true">
            <PatternLayout pattern="[%d{HH:mm:ss}] [%t/%level] [%c{1.}]: %msg%n" />
        </Console>
        <RollingRandomAccessFile name="File" fileName="logs/latest.log" filePattern="logs/%d{yyyy-MM-dd}-%i.log.gz">
            <PatternLayout pattern="[%d{ddMMMyyyy HH:mm:ss.SSS}] [%t/%level] [%c{2.}]: %msg%n" />
            <Policies>
                <TimeBasedTriggeringPolicy />
                <OnStartupTriggeringPolicy />
            </Policies>
            <DefaultRolloverStrategy max="99" fileIndex="min" />
        </RollingRandomAccessFile>
    </Appenders>
    <Loggers>
        <Root level="info">
            <AppenderRef ref="Console" />
            <AppenderRef ref="File" />
        </Root>
    </Loggers>
</Configuration>"""


__all__ = [
    "FALLBACK_LOG4J_XML",
    "LOG4J_INCOMPATIBLE_MARKERS",
    "MAVEN_REPOS",
    "MODLAUNCHER_FALLBACK_VERSIONS",
    "NETWORK_FAILURE_MARKERS",
]
