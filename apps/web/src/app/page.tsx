import { LandingHeader } from "@/components/landing/header";
import { Hero } from "@/components/landing/hero";
import { WorkflowDemo } from "@/components/landing/workflow-demo";
import {
  CallToAction,
  Capabilities,
  ExampleWorkflow,
  Footer,
  HowItWorks,
  Security,
} from "@/components/landing/sections";

export default function HomePage() {
  return (
    <>
      <LandingHeader />
      <main className="flex-1">
        <Hero />
        <WorkflowDemo />
        <HowItWorks />
        <Capabilities />
        <ExampleWorkflow />
        <Security />
        <CallToAction />
      </main>
      <Footer />
    </>
  );
}
