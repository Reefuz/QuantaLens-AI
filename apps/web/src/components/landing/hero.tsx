"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Hero() {
  return (
    <section className="mx-auto max-w-6xl px-5 pt-20 pb-16 md:pt-28">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
        className="max-w-3xl"
      >
        <p className="mb-5 text-sm font-medium text-brand">See Beyond the Data.</p>
        <h1 className="text-4xl font-semibold tracking-tight text-balance md:text-6xl">
          Your Data Has Answers. Let&apos;s Find Them.
        </h1>
        <p className="mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground text-pretty">
          Transform messy datasets into meaningful business intelligence. Ask questions, run analyses, inspect the code
          and uncover insights with an AI-powered analytical workspace.
        </p>
        <div className="mt-9 flex flex-wrap items-center gap-3">
          <Link href="/register" className={cn(buttonVariants({ size: "lg" }), "h-10 px-4 text-sm")}>
            Start Analysing <ArrowRight className="size-4" />
          </Link>
          <a href="#workflow" className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-10 px-4 text-sm")}>
            Explore Demo
          </a>
        </div>
      </motion.div>
    </section>
  );
}
